#!/usr/bin/env python3
"""ACC hero scenario, end to end, in a single process.

Runs exactly the Doc 06 demo:
  1. Normal mission        -> fleet at work, below the autonomous threshold
  2. Supplier failure      -> AT_RISK
  3. Failure Twin          -> options evaluated, best PERMITTED option
  4. Authority boundary    -> human approval requested (18 000 $)
  5. Runtime interruption  -> state survives
  6. Resume + approval     -> purchase executed, mission COMPLETED

Usage:  python scripts/run_hero_scenario.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from apps.api.core.config import Settings
from apps.api.repositories.factory import reset_store
from apps.api.services.container import build_container, set_container
from domain import ids
from domain.enums import MissionStatus
from mock_enterprise.main import app as mock_app
from mock_enterprise.state import STATE

GREEN, RED, YELLOW, BLUE, BOLD, RESET = (
    "\033[92m", "\033[91m", "\033[93m", "\033[94m", "\033[1m", "\033[0m"
)


def step(n: int, title: str) -> None:
    print(f"\n{BOLD}{BLUE}── ETAPE {n} ── {title}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}▲{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}✗{RESET} {msg}")


async def main() -> int:
    reset_store()
    ids.reset_counters()
    STATE.reset()

    # `_env_file=None`: the demo scenario must be reproducible identically,
    # whatever `.env` happens to be present on the machine.
    settings = Settings(
        _env_file=None,
        acc_persistence="memory", acc_event_bus="inproc",
        acc_agent_mode="deterministic", acc_model_armor="heuristic",
        acc_enterprise_base_url="http://mock-enterprise",
    )
    container = build_container(
        settings, enterprise_transport=httpx.ASGITransport(app=mock_app)
    )
    set_container(container)
    await container.startup()
    engine, store = container.engine, container.store

    try:
        # --- 1. Mission normale --------------------------------------------
        step(1, "Mission normale — la flotte travaille dans son autorite")
        mission = await engine.create_mission("Protect production schedule")
        ok(f"Mission {mission.mission_id} creee "
           f"({mission.context.required_units} unites, "
           f"echeance {mission.context.deadline_hours}h)")
        agents = await container.registry.list()
        ok(f"Flotte enregistree : {', '.join(a.agent_id for a in agents)}")

        # --- 2. Panne fournisseur ------------------------------------------
        step(2, "Panne fournisseur injectee — SUP-A renvoie 503")
        STATE.suppliers["SUP-A"].failing = True
        STATE.suppliers["SUP-A"].status = "UNAVAILABLE"
        warn("SUP-A hors service (declenche par l'operateur, pas par hasard)")

        await engine.start(mission.mission_id)
        await container.events.drain(timeout=60)

        mission = await store.get_mission(mission.mission_id)
        recoveries = await store.list_recoveries(mission.mission_id)
        if not recoveries:
            fail("Aucune recovery declenchee")
            return 1
        rec = recoveries[0]
        ok(f"Mission passee par AT_RISK -> RECOVERING (statut : {mission.status.value})")

        # --- 3. Failure Twin ------------------------------------------------
        step(3, "Failure Twin — options evaluees et FILTREES")
        print(f"     Diagnostic : {rec.diagnosis}")
        for option in rec.options:
            mark = f"{GREEN}PERMISE{RESET}" if option.permitted else f"{RED}NON PERMISE{RESET}"
            reason = f" — {option.denial_reason}" if option.denial_reason else ""
            print(f"     • {option.label:<32} [{mark}]{reason}")
        ok(f"Strategie retenue : {rec.selected_option.value} "
           f"-> {rec.selected_parameters.get('supplier_id')}")
        print(f"     Justification : {rec.reason}")

        # --- 4. Frontiere d'autorite ----------------------------------------
        step(4, "Frontiere d'autonomie — l'achat depasse le seuil")
        pending = await container.approvals.list(mission.mission_id, "PENDING")
        if not pending:
            fail("Aucune approbation en attente : la frontiere n'a pas fonctionne")
            return 1
        approval = next((a for a in pending if a.action == "purchase.execute"), pending[0])
        amount = f"{approval.amount:,.0f} USD" if approval.amount else "montant n/a"
        ok(f"Mission en {mission.status.value}")
        ok(f"Approbation {approval.approval_id} requise : {approval.action} "
           f"pour {amount}")
        print(f"     Motif : {approval.reason}")

        # --- 5. Interruption de runtime -------------------------------------
        step(5, "Interruption du runtime — l'etat de mission survit")
        await engine.interrupt(mission.mission_id)
        checkpoints = await container.checkpoints.list(mission.mission_id)
        ok(f"{len(checkpoints)} checkpoints persistes, dernier : "
           f"{checkpoints[-1].checkpoint_id} ({checkpoints[-1].label})")

        resumed = await engine.resume(mission.mission_id)
        await container.events.drain(timeout=30)
        ok(f"Reprise effectuee — statut {resumed.status.value} "
           f"(approbation toujours en attente, aucune tache rejouee)")

        # --- 6. Approbation + execution -------------------------------------
        step(6, "Autorite humaine accordee — la mission se termine")
        await container.approvals.decide(approval.approval_id, True, "operator",
                                         "Continuite de production prioritaire")
        await container.events.drain(timeout=60)

        mission = await store.get_mission(mission.mission_id)
        ctx = mission.context
        if mission.status is MissionStatus.COMPLETED:
            ok(f"Mission {mission.status.value} — fournisseur {ctx.selected_supplier}, "
               f"commande {ctx.purchase_id}, montant {ctx.purchase_amount:,.0f} USD")
        else:
            fail(f"Statut final inattendu : {mission.status.value}")
            return 1

        # --- Preuves --------------------------------------------------------
        step(7, "Preuves de gouvernance")
        metrics = await container.metrics.for_mission(mission.mission_id)
        audits = await store.list_audit(mission.mission_id)
        fleet = await container.metrics.fleet_summary()
        ok(f"Mission Continuity Rate : {fleet['mission_continuity_rate']}%")
        ok(f"Recovery : {metrics.recovery_success}/{metrics.recovery_attempts} reussie(s) "
           f"en {metrics.recovery_duration_s}s")
        ok(f"Approbations : {metrics.approvals_granted}/{metrics.approvals_requested}, "
           f"latence {metrics.approval_latency_s}s")
        ok(f"Violations de politique : {metrics.policy_violations} "
           f"(exigence produit : 0)")
        ok(f"Executions dupliquees : {metrics.duplicate_executions} "
           f"(idempotence respectee)")
        ok(f"Piste d'audit : {len(audits)} entrees, "
           f"{metrics.evidence['checkpoints']} checkpoints, "
           f"{metrics.evidence['events']} evenements")

        purchases = list(STATE.purchases.values())
        if len(purchases) != 1:
            fail(f"{len(purchases)} achats executes — l'idempotence a echoue")
            return 1
        ok(f"Exactement 1 achat cote entreprise : {purchases[0]['purchase_id']}")

        print(f"\n{BOLD}{GREEN}THE AGENT CAN FAIL. THE MISSION DOESN'T HAVE TO.{RESET}\n")
        return 0
    finally:
        await container.shutdown()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
