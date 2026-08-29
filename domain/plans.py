"""Mission plans — deterministic decomposition into tasks (Doc 08 §4).

The LLM does not decide the mission plan. It decides *within* a task.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from domain.enums import Priority


@dataclass(frozen=True)
class TaskTemplate:
    type: str
    title: str
    agent_id: str
    order: int
    depends_on_types: tuple[str, ...] = ()
    priority: Priority = Priority.HIGH


@dataclass(frozen=True)
class MissionTemplate:
    key: str
    objective: str
    stage_by_task_type: dict[str, str]
    tasks: tuple[TaskTemplate, ...] = field(default_factory=tuple)


PROTECT_PRODUCTION = MissionTemplate(
    key="protect-production",
    objective="Protect production schedule",
    stage_by_task_type={
        "supply_analysis": "supply_analysis",
        "risk_assessment": "risk_assessment",
        "procurement_plan": "procurement_planning",
        "procurement_execute": "procurement_execution",
    },
    tasks=(
        TaskTemplate("supply_analysis", "Supplier availability analysis",
                     "supply-agent", 1),
        TaskTemplate("risk_assessment", "Supply risk assessment",
                     "risk-agent", 2, ("supply_analysis",)),
        TaskTemplate("procurement_plan", "Purchase plan preparation",
                     "procurement-agent", 3, ("risk_assessment",)),
        TaskTemplate("procurement_execute", "Authorised purchase execution",
                     "procurement-agent", 4, ("procurement_plan",)),
    ),
)

TEMPLATES: dict[str, MissionTemplate] = {PROTECT_PRODUCTION.key: PROTECT_PRODUCTION}


def get_template(key: str = "protect-production") -> MissionTemplate:
    return TEMPLATES.get(key, PROTECT_PRODUCTION)
