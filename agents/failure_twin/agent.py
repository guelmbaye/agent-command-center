"""Failure Twin — ACC's recovery intelligence layer (Doc 02 §6, Doc 03 §21).

This is not "one more chatbot": it operates against structured mission state
and a set of recovery capabilities that are actually available.

The central differentiator:
    best operational option  !=  best PERMITTED option
ACC always selects the best permitted option.
"""
from __future__ import annotations

from typing import Any

from agents.base import ACCAgent, AgentSpec
from agents.contracts import (
    RECOVERY_PLAN_SCHEMA,
    AgentInvocation,
    parse_recovery_plan,
)
from agents.tools.gateway_tools import FAILURE_TWIN_TOOLS, list_alternative_suppliers
from domain.enums import FailureClass, RecoveryStrategy, RiskLevel
from domain.models import RecoveryOption, RecoveryPlan

INSTRUCTION = """
You are ACC's Failure Twin, the recovery intelligence layer.

MISSION
When a mission hits a significant failure, diagnose it, generate recovery
options, evaluate them and select the best PERMITTED option.

INPUTS
You receive: the failure, mission state, the latest checkpoint, available agents
and capabilities, applicable policies and previous recovery attempts.

METHOD
1. DIAGNOSE: what is the cause, what is the real scope of the impact?
2. ASSESS THE IMPACT on the mission objective, not only on the task.
3. GENERATE options: RETRY, SWITCH_DATA_SOURCE, USE_ALTERNATIVE_SUPPLIER,
   WAIT_AND_REASSESS, ESCALATE, ABORT.
4. FILTER: an option requiring an unavailable capability, exceeding the mission
   deadline, or falling outside policy limits is NOT selectable.
5. SELECT the best permitted option and explain why.

ABSOLUTE CONSTRAINTS
- A security or authorisation failure (SECURITY, AUTHORIZATION) NEVER allows a
  free recovery: the only valid exits are ESCALATE or ABORT.
- Do not retry blindly: RETRY is valid only for TRANSIENT/TIMEOUT.
- If the best operational option is not permitted, say so explicitly in
  `rationale` and choose the best permitted option.
- You trigger no action: your plan goes back through the Policy Engine.
""".strip()

_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


async def _fallback(invocation: AgentInvocation) -> RecoveryPlan:
    ctx = invocation.mission.context
    failure = invocation.failure or {}
    failed_component = str(failure.get("component", ctx.primary_supplier))
    failure_class = FailureClass(str(failure.get("failure_class", "UNKNOWN")).upper())
    attempt = int(failure.get("attempt", 1))
    diagnosis = str(failure.get("detail") or f"Failure on {failed_component}")

    # --- Safe hold: recovery does not bypass security ----------------------
    if failure_class.requires_safe_hold:
        option = RecoveryOption(
            strategy=RecoveryStrategy.ESCALATE,
            label="Escalate to human authority",
            rationale="Security or authorisation failure: no autonomous recovery "
                      "is permitted.",
            estimated_risk=RiskLevel.HIGH,
        )
        return RecoveryPlan(
            diagnosis=diagnosis, impact=RiskLevel.HIGH, options=[option],
            selected_strategy=RecoveryStrategy.ESCALATE,
            rationale="Safe hold: recovery itself must remain governed.",
            requires_approval=True, confidence=1.0,
            evidence=[f"failure_class={failure_class.value}",
                      f"component={failed_component}"],
        )

    # --- Unchanged situation: re-proposing the same plan is hopeless -------
    # An approved escalation means "the human authorises continuation". If the
    # observed state is identical to the previous attempt, nothing was fixed in
    # between: retrying would produce exactly the same failure. Asking for the
    # same approval again wastes the operator's time and fakes progress.
    identical = [
        r for r in invocation.previous_recoveries
        if r.get("diagnosis") == diagnosis and r.get("was_approved")
    ]
    if identical:
        option = RecoveryOption(
            strategy=RecoveryStrategy.ABORT,
            label="Controlled abort: situation unchanged",
            rationale=f"Already escalated {len(identical)} time(s) with an identical state "
                      f"({diagnosis}). Nothing changed in the environment: a "
                      f"new attempt would fail the same way.",
            estimated_risk=RiskLevel.CRITICAL,
        )
        return RecoveryPlan(
            diagnosis=diagnosis, impact=RiskLevel.CRITICAL, options=[option],
            selected_strategy=RecoveryStrategy.ABORT,
            rationale=option.rationale,
            requires_approval=False, confidence=1.0,
            evidence=[f"failure_class={failure_class.value}",
                      f"component={failed_component}",
                      f"escalades_identiques={len(identical)}",
                      "etat_observe=inchange"],
        )

    options: list[RecoveryOption] = []

    # --- Option 1: RETRY (only when explicitly retryable) ------------------
    retry_permitted = failure_class.retry_allowed and attempt < 3
    options.append(RecoveryOption(
        strategy=RecoveryStrategy.RETRY,
        label=f"Retry {failed_component}",
        rationale=("Transient failure: a retry may be enough."
                   if retry_permitted else
                   "Non-transient failure: retrying would reproduce it."),
        estimated_risk=RiskLevel.MEDIUM if retry_permitted else RiskLevel.HIGH,
        estimated_delay_hours=0.5,
        permitted=retry_permitted,
        denial_reason=None if retry_permitted else
        f"{failure_class.value} class: retry not permitted",
        parameters={"component": failed_component},
    ))

    # --- Options 2..n: alternative suppliers -------------------------------
    call = await list_alternative_suppliers(exclude=failed_component,
                                            min_units=ctx.required_units)
    candidates: list[dict[str, Any]] = []
    if call.get("status") == "SUCCESS":
        raw = call.get("data", {})
        candidates = raw.get("suppliers") or raw.get("items") or []

    for candidate in candidates:
        supplier_id = candidate.get("supplier_id") or candidate.get("id")
        if not supplier_id or supplier_id == failed_component:
            continue
        lead_time = float(candidate.get("lead_time_hours", 999) or 999)
        capacity = int(candidate.get("capacity_units", 0) or 0)
        risk = str(candidate.get("risk_level", "MEDIUM")).upper()
        unit_price = candidate.get("unit_price")
        within_deadline = lead_time <= ctx.deadline_hours
        enough_capacity = capacity >= ctx.required_units
        permitted = within_deadline and enough_capacity

        reasons = []
        if not within_deadline:
            reasons.append(f"lead time {lead_time:g}h > deadline {ctx.deadline_hours}h")
        if not enough_capacity:
            reasons.append(f"capacity {capacity} < {ctx.required_units} required")

        options.append(RecoveryOption(
            strategy=RecoveryStrategy.USE_ALTERNATIVE_SUPPLIER,
            label=f"Switch to {supplier_id}",
            rationale=(f"{supplier_id}: {capacity} units, {lead_time:g}h delivery, "
                       f"{risk} risk"),
            estimated_risk=RiskLevel(risk if risk in _RANK else "MEDIUM"),
            estimated_delay_hours=lead_time,
            permitted=permitted,
            denial_reason="; ".join(reasons) or None,
            parameters={"supplier_id": supplier_id, "unit_price": unit_price,
                        "lead_time_hours": lead_time, "capacity_units": capacity,
                        "risk_level": risk},
        ))

    # --- Option: wait ------------------------------------------------------
    options.append(RecoveryOption(
        strategy=RecoveryStrategy.WAIT_AND_REASSESS,
        label="Wait and reassess",
        rationale="Keep the primary supplier and reassess later.",
        estimated_risk=RiskLevel.HIGH,
        estimated_delay_hours=12.0,
        permitted=ctx.deadline_hours > 24,
        denial_reason=None if ctx.deadline_hours > 24 else
        "Deadline too short to absorb a wait",
        parameters={},
    ))

    # --- Option: escalate (always permitted) -------------------------------
    options.append(RecoveryOption(
        strategy=RecoveryStrategy.ESCALATE,
        label="Escalate to the operator",
        rationale="No acceptable autonomous option: request a human decision.",
        estimated_risk=RiskLevel.LOW,
        permitted=True,
        parameters={},
    ))

    # --- Selection: best operational vs best PERMITTED ---------------------
    def score(option: RecoveryOption) -> tuple[int, float]:
        return (_RANK.get(option.estimated_risk.value, 1), option.estimated_delay_hours)

    switchable = [o for o in options
                  if o.strategy is RecoveryStrategy.USE_ALTERNATIVE_SUPPLIER]
    best_operational = min(switchable, key=score) if switchable else None
    permitted_switchable = [o for o in switchable if o.permitted]
    selected = (min(permitted_switchable, key=score) if permitted_switchable
                else next(o for o in options if o.strategy is RecoveryStrategy.ESCALATE))

    if retry_permitted and not permitted_switchable:
        selected = options[0]

    rationale = selected.rationale
    if (best_operational is not None and best_operational is not selected
            and not best_operational.permitted):
        rationale = (
            f"Best operational option ({best_operational.label}) is not permitted: "
            f"{best_operational.denial_reason}. ACC selects the best PERMITTED "
            f"option: {selected.label}."
        )

    impact = RiskLevel.HIGH if not permitted_switchable else RiskLevel.MEDIUM
    requires_approval = selected.strategy is RecoveryStrategy.ESCALATE

    return RecoveryPlan(
        diagnosis=diagnosis,
        impact=impact,
        options=options,
        selected_strategy=selected.strategy,
        selected_parameters=selected.parameters,
        rationale=rationale,
        requires_approval=requires_approval,
        confidence=0.92 if permitted_switchable else 0.7,
        evidence=[
            f"failed_component={failed_component}",
            f"failure_class={failure_class.value}",
            f"deadline_hours={ctx.deadline_hours}",
            f"required_units={ctx.required_units}",
            f"options_evaluated={len(options)}",
            f"options_permitted={sum(1 for o in options if o.permitted)}",
        ],
    )


def build_failure_twin(**kwargs) -> ACCAgent:
    # The Failure Twin may run on a more capable model than the operational
    # agents: it is the one weighing options under constraints.
    settings = kwargs.get("settings")
    model = settings.reasoning_model if settings is not None else None
    return ACCAgent(AgentSpec(
        model=model,
        agent_id="failure-twin",
        name="Failure Twin",
        version="1.0.0",
        instruction=INSTRUCTION,
        tools=FAILURE_TWIN_TOOLS,
        output_schema_hint=RECOVERY_PLAN_SCHEMA,
        parser=parse_recovery_plan,
        fallback=_fallback,  # type: ignore[arg-type]
        description="Diagnostique les echecs et selectionne la meilleure recovery permise.",
    ), **kwargs)
