"""Fleet input/output contracts (Doc 02 §14, Doc 07 §7).

One output schema for every agent: this stops a downstream agent from having to
parse natural language produced by an upstream one.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from domain.enums import AgentResultStatus, FailureClass, RecoveryStrategy, RiskLevel
from domain.models import AgentIdentity, AgentResult, Mission, RecoveryOption, RecoveryPlan


@dataclass
class AgentInvocation:
    """Compact context handed to an agent — never the full history (Doc 04 §14)."""
    identity: AgentIdentity
    mission: Mission
    task_type: str
    task_title: str = ""
    memory_recall: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    failure: dict[str, Any] | None = None
    previous_recoveries: list[dict[str, Any]] = field(default_factory=list)
    available_agents: list[str] = field(default_factory=list)
    available_capabilities: list[str] = field(default_factory=list)
    policy_summary: dict[str, Any] = field(default_factory=dict)

    def to_prompt_payload(self) -> dict[str, Any]:
        ctx = self.mission.context
        payload: dict[str, Any] = {
            "mission": {
                "mission_id": self.mission.mission_id,
                "objective": self.mission.objective,
                "status": self.mission.status.value,
                "stage": self.mission.current_stage,
                "deadline_hours": ctx.deadline_hours,
                "required_units": ctx.required_units,
                "primary_supplier": ctx.primary_supplier,
                "fallback_suppliers": ctx.fallback_suppliers,
                "selected_supplier": ctx.selected_supplier,
                "constraints": ctx.constraints,
            },
            "task": {"type": self.task_type, "title": self.task_title},
            "inputs": self.inputs,
            "mission_memory": self.memory_recall,
            "available_capabilities": self.available_capabilities,
        }
        if self.failure:
            payload["failure"] = self.failure
        if self.previous_recoveries:
            payload["previous_recovery_attempts"] = self.previous_recoveries
        if self.available_agents:
            payload["available_agents"] = self.available_agents
        if self.policy_summary:
            payload["policy_boundaries"] = self.policy_summary
        return payload


# --- Schemas demandes au modele ---------------------------------------------
AGENT_RESULT_SCHEMA = """{
  "status": "SUCCESS | PARTIAL | RETRYABLE_FAILURE | NON_RETRYABLE_FAILURE | BLOCKED",
  "finding": "constat factuel, une phrase",
  "recommendation": "recommandation ou null",
  "confidence": 0.0,
  "evidence": ["fait verifiable 1", "fait verifiable 2"],
  "data": {},
  "next_action": "capacite suggeree ou null",
  "requires_approval": false
}"""

RECOVERY_PLAN_SCHEMA = """{
  "diagnosis": "cause et perimetre de l'echec",
  "impact": "LOW | MEDIUM | HIGH | CRITICAL",
  "options": [
    {"strategy": "RETRY | SWITCH_AGENT | SWITCH_DATA_SOURCE | USE_ALTERNATIVE_SUPPLIER | WAIT_AND_REASSESS | ESCALATE | ABORT",
     "label": "titre court",
     "rationale": "pourquoi cette option",
     "estimated_risk": "LOW | MEDIUM | HIGH | CRITICAL",
     "estimated_delay_hours": 0,
     "parameters": {}}
  ],
  "selected_strategy": "strategie retenue",
  "selected_parameters": {},
  "rationale": "pourquoi cette strategie est la meilleure PERMISE",
  "requires_approval": false,
  "confidence": 0.0,
  "evidence": []
}"""


# --- Parsing robuste ---------------------------------------------------------
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """The model may wrap the JSON in prose: extract without breaking."""
    if not text:
        return None
    candidates: list[str] = []
    fenced = _FENCE.findall(text)
    candidates.extend(fenced)
    stripped = text.strip()
    candidates.append(stripped)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start:end + 1])
    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def parse_agent_result(text: str) -> AgentResult | None:
    payload = extract_json(text)
    if payload is None:
        return None
    payload.setdefault("status", "SUCCESS")
    if isinstance(payload.get("status"), str):
        payload["status"] = payload["status"].upper()
    try:
        return AgentResult.model_validate(payload)
    except ValidationError:
        return AgentResult(
            status=AgentResultStatus.PARTIAL,
            finding=str(payload.get("finding", ""))[:500],
            recommendation=payload.get("recommendation"),
            confidence=float(payload.get("confidence") or 0.0),
            data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
        )


def parse_recovery_plan(text: str) -> RecoveryPlan | None:
    payload = extract_json(text)
    if payload is None:
        return None
    try:
        options = [
            RecoveryOption(
                strategy=RecoveryStrategy(str(o.get("strategy", "ESCALATE")).upper()),
                label=str(o.get("label", "")),
                rationale=str(o.get("rationale", "")),
                estimated_risk=RiskLevel(str(o.get("estimated_risk", "MEDIUM")).upper()),
                estimated_delay_hours=float(o.get("estimated_delay_hours") or 0),
                parameters=o.get("parameters") if isinstance(o.get("parameters"), dict) else {},
            )
            for o in payload.get("options", []) if isinstance(o, dict)
        ]
        return RecoveryPlan(
            diagnosis=str(payload.get("diagnosis", "")),
            impact=RiskLevel(str(payload.get("impact", "HIGH")).upper()),
            options=options,
            selected_strategy=RecoveryStrategy(
                str(payload.get("selected_strategy", "ESCALATE")).upper()
            ),
            selected_parameters=(
                payload.get("selected_parameters")
                if isinstance(payload.get("selected_parameters"), dict) else {}
            ),
            rationale=str(payload.get("rationale", "")),
            requires_approval=bool(payload.get("requires_approval", False)),
            confidence=float(payload.get("confidence") or 0.0),
            evidence=[str(e) for e in payload.get("evidence", [])],
        )
    except (ValidationError, ValueError, KeyError):
        return None


def failure_result(detail: str, failure_class: FailureClass) -> AgentResult:
    status = (AgentResultStatus.RETRYABLE_FAILURE if failure_class.retry_allowed
              else AgentResultStatus.NON_RETRYABLE_FAILURE)
    if failure_class.requires_safe_hold:
        status = AgentResultStatus.BLOCKED
    return AgentResult(
        status=status, finding=detail, confidence=1.0,
        failure_class=failure_class, failure_detail=detail,
    )
