#!/usr/bin/env python3
"""Functional coverage audit against the blueprint Definitions of Done.

Every requirement is linked to a REAL test, identified by its pytest node id.
The script fails if a referenced test does not exist: you cannot tick a box by
simply renaming a test.

Usage:  python scripts/audit_coverage.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (document, requirement, test that proves it)
REQUIREMENTS: list[tuple[str, str, str]] = [
    # --- Doc 10 §14: validation matrix -------------------------------------
    ("Doc10 matrice", "Mission normale -> COMPLETED",
     "tests/scenarios/test_hero_scenario.py::test_nominal_mission_completes_autonomously"),
    ("Doc10 matrice", "Panne fournisseur -> RECOVERING",
     "tests/scenarios/test_hero_scenario.py::test_supplier_failure_triggers_governed_recovery"),
    ("Doc10 matrice", "Repli valide -> RECOVERED",
     "tests/scenarios/test_hero_scenario.py::test_approval_completes_the_mission"),
    ("Doc10 matrice", "Achat eleve -> APPROVAL_REQUIRED",
     "tests/scenarios/test_hero_scenario.py::test_authority_boundary_stops_the_purchase"),
    ("Doc10 matrice", "Approbation accordee -> EXECUTE",
     "tests/scenarios/test_hero_scenario.py::test_approval_completes_the_mission"),
    ("Doc10 matrice", "Approbation rejetee -> SAFE HOLD",
     "tests/scenarios/test_hero_scenario.py::test_rejection_produces_a_safe_hold"),
    ("Doc10 matrice", "Instruction malveillante -> BLOCKED",
     "tests/scenarios/test_hero_scenario.py::test_malicious_supplier_content_does_not_change_authority"),
    ("Doc10 matrice", "Achat duplique -> aucune double execution",
     "tests/integration/test_gateway.py::test_idempotency_prevents_double_purchase"),
    ("Doc10 matrice", "Redemarrage agent -> RESUME",
     "tests/scenarios/test_hero_scenario.py::test_runtime_interruption_preserves_mission_state"),
    ("Doc10 matrice", "Echec de recovery -> FAILED + explicable",
     "tests/scenarios/test_edge_paths.py::test_rejected_escalation_fails_explainably"),

    # --- Doc 02: governed fleet --------------------------------------------
    ("Doc02 flotte", "Capacites declarees et opposables",
     "tests/integration/test_gateway.py::test_agent_without_capability_is_refused"),
    ("Doc02 flotte", "Identite requise avant execution",
     "tests/integration/test_gateway.py::test_incomplete_identity_is_refused"),
    ("Doc02 flotte", "FAILED -> EXECUTING interdit sans validation",
     "tests/unit/test_state_machine.py::test_failed_agent_cannot_execute_silently"),
    ("Doc02 flotte", "Resultat d'agent structure, jamais du texte libre",
     "tests/unit/test_contracts.py::test_parse_agent_result_normalises_status"),

    # --- Doc 03: security and governance -----------------------------------
    ("Doc03 securite", "Seuils d'autorite d'achat",
     "tests/unit/test_policy_engine.py::test_purchase_thresholds"),
    ("Doc03 securite", "Refus par defaut",
     "tests/unit/test_policy_engine.py::test_unknown_capability_defaults_to_deny"),
    ("Doc03 securite", "Ressources interdites",
     "tests/unit/test_policy_engine.py::test_forbidden_resource_always_denied"),
    ("Doc03 securite", "La recovery est elle-meme gouvernee",
     "tests/unit/test_policy_engine.py::test_high_risk_recovery_requires_approval"),
    ("Doc03 securite", "Un agent n'approuve pas sa propre action",
     "tests/integration/test_memory_and_approvals.py::test_agent_cannot_approve_its_own_action"),
    ("Doc03 securite", "Injection de prompt bloquee",
     "tests/unit/test_model_armor.py::test_injection_variants_detected"),
    ("Doc03 securite", "Tool poisoning neutralise",
     "tests/integration/test_gateway.py::test_tool_poisoning_is_neutralised"),
    ("Doc03 securite", "Agent suspendu -> arret securise de la mission",
     "tests/scenarios/test_edge_paths.py::test_suspended_agent_stops_the_mission_safely"),
    ("Doc03 securite", "Approbation expiree n'autorise rien",
     "tests/scenarios/test_edge_paths.py::test_expired_approval_cannot_be_granted"),
    ("Doc03 securite", "Toute action consequente est auditee",
     "tests/integration/test_gateway.py::test_every_call_leaves_an_audit_record"),

    # --- Doc 04: memory and long-running operations ------------------------
    ("Doc04 memoire", "Etat survit a l'interruption de runtime",
     "tests/scenarios/test_hero_scenario.py::test_runtime_interruption_preserves_mission_state"),
    ("Doc04 memoire", "La reprise ne rejoue pas le travail termine",
     "tests/scenarios/test_hero_scenario.py::test_resume_does_not_replay_completed_work"),
    ("Doc04 memoire", "Approbation durable pendant une attente longue",
     "tests/scenarios/test_edge_paths.py::test_delayed_approval_still_completes_the_mission"),
    ("Doc04 memoire", "Memoire isolee par mission",
     "tests/integration/test_memory_and_approvals.py::test_memory_is_scoped_to_its_mission"),
    ("Doc04 memoire", "Donnees sensibles jamais transmises a un agent",
     "tests/integration/test_memory_and_approvals.py::test_confidential_memory_never_reaches_an_agent"),
    ("Doc04 memoire", "Compaction sans perte d'etat autoritatif",
     "tests/unit/test_alerting_and_metrics.py::test_context_compaction_never_replaces_state"),
    ("Doc04 memoire", "Contexte de recovery porte les tentatives precedentes",
     "tests/scenarios/test_edge_paths.py::test_recovery_context_carries_previous_attempts"),

    # --- Doc 05: observability and reliability -----------------------------
    ("Doc05 observabilite", "Chronologie et chainage d'integrite",
     "tests/scenarios/test_hero_scenario.py::test_timeline_and_evidence_are_exposed"),
    ("Doc05 observabilite", "Metriques de fiabilite calculees",
     "tests/unit/test_alerting_and_metrics.py::test_reliability_metrics_are_populated"),
    ("Doc05 observabilite", "Alertes orientees mission, sans sur-alerte",
     "tests/unit/test_alerting_and_metrics.py::test_routine_approval_does_not_raise_a_critical_alert"),
    ("Doc05 observabilite", "Piste d'audit complete apres recovery",
     "tests/scenarios/test_hero_scenario.py::test_audit_trail_and_metrics_are_complete"),
    ("Doc05 observabilite", "Classification d'echec et regles de retry",
     "tests/unit/test_failure_classifier.py::test_retry_never_allowed_on_security_failures"),
    ("Doc05 observabilite", "Un log ne peut pas faire tomber une mission",
     "tests/unit/test_logging.py::test_reserved_field_names_do_not_raise"),

    # --- Doc 07 / 08: architecture, data, chaos ----------------------------
    ("Doc07 chaos", "Timeout modele -> repli, jamais de blocage",
     "tests/integration/test_adk_path.py::test_timeout_triggers_fallback"),
    ("Doc07 chaos", "Panne de dependance classifiee",
     "tests/integration/test_gateway.py::test_tool_failure_is_classified"),
    ("Doc07 chaos", "Redelivrance Pub/Sub : aucune re-execution",
     "tests/integration/test_concurrency.py::test_replaying_processed_events_is_inert"),
    ("Doc07 chaos", "Livraison concurrente : une execution par tache",
     "tests/integration/test_concurrency.py::test_concurrent_delivery_runs_each_task_once"),
    ("Doc07 chaos", "Recovery repetee apres un second echec",
     "tests/scenarios/test_edge_paths.py::test_second_failure_triggers_a_second_governed_recovery"),
    ("Doc07 architecture", "Le mode d'agent ne change pas la gouvernance",
     "tests/integration/test_adk_path.py::test_adk_mode_still_hits_the_authority_boundary"),
    ("Doc08 donnees", "Concurrence optimiste sur l'etat de mission",
     "tests/integration/test_concurrency.py::test_stale_mission_write_is_rejected"),
    ("Doc08 donnees", "Verrou de tache exclusif",
     "tests/integration/test_concurrency.py::test_claim_is_exclusive"),
    ("Doc08 donnees", "Contrat d'erreur unifie",
     "tests/integration/test_api.py::test_unknown_mission_returns_contract_error"),
    ("Doc08 donnees", "Cycle de vie complet via l'API",
     "tests/integration/test_api.py::test_mission_lifecycle_over_http"),

    # --- Doc 06: the demo script must stay true ----------------------------
    ("Doc06 demo", "L'ordre prescrit produit bien le scenario hero",
     "tests/scenarios/test_demo_script.py::test_arming_before_launch_produces_the_hero_story"),
    ("Doc06 demo", "Les chiffres annonces au jury sont exacts",
     "tests/scenarios/test_demo_script.py::test_recovery_shows_five_options_two_refused"),
    ("Doc06 demo", "Les prix cites viennent des systemes simules",
     "tests/scenarios/test_demo_script.py::test_script_prices_match_the_enterprise_state"),
    ("Doc06 demo", "Les libelles cites sont ceux de l'interface",
     "tests/scenarios/test_demo_script.py::test_script_uses_the_current_metric_labels"),
    ("Doc06 demo", "L'injection hostile armee a temps est visible",
     "tests/scenarios/test_demo_script.py::test_injection_armed_before_launch_is_visible"),
    ("Doc06 demo", "Les pieges d'ordonnancement sont documentes",
     "tests/scenarios/test_demo_script.py::test_script_documents_the_ordering_trap"),
    ("Doc06 demo", "La variante « lucidite » se comporte comme ecrit",
     "tests/scenarios/test_demo_script.py::test_lucidity_variant_behaves_as_scripted"),

    # --- Doc 04: checkpoints must tell the truth ---------------------------
    ("Doc04 memoire", "Les checkpoints decrivent ce qui s'est reellement passe",
     "tests/scenarios/test_checkpoint_labels.py::test_nominal_mission_never_mentions_recovery"),
    ("Doc04 memoire", "Toute etape de checkpoint a un libelle lisible",
     "tests/scenarios/test_checkpoint_labels.py::test_every_checkpoint_stage_has_a_readable_label"),

    # --- Doc 09: cost control (constrained hackathon budget) ---------------
    ("Doc09 cloud", "Aucun service ne facture a l'inactivite",
     "tests/unit/test_cost_guardrails.py::test_every_cloud_run_service_scales_to_zero"),
    ("Doc09 cloud", "Aucune ressource facturant a l'heure",
     "tests/unit/test_cost_guardrails.py::test_no_continuously_billing_resource"),
    ("Doc09 cloud", "Aucun modele couteux par defaut",
     "tests/unit/test_cost_guardrails.py::test_no_agent_uses_a_pro_model_by_default"),
    ("Doc09 cloud", "La facture est ventilable par composant",
     "tests/unit/test_cost_guardrails.py::test_cost_labels_allow_billing_breakdown"),

    # --- Contest rules: Stage One is a pass/fail ---------------------------
    ("Reglement", "Modele Gemini 3.5 ou plus recent (obligatoire)",
     "tests/unit/test_contest_compliance.py::test_configured_model_meets_the_mandatory_minimum"),
    ("Reglement", "Framework d'agent Google + service Google Cloud",
     "tests/unit/test_contest_compliance.py::test_mandatory_google_stack_is_present"),
    ("Reglement", "Les sept primitives Fortified Enterprise Fleet",
     "tests/unit/test_contest_compliance.py::test_fortified_fleet_primitives_are_all_implemented"),
    ("Reglement", "L'application fonctionne en anglais",
     "tests/unit/test_contest_compliance.py::test_ui_strings_are_english"),
    ("Reglement", "Schema d'architecture fourni",
     "tests/unit/test_contest_compliance.py::test_architecture_diagram_is_provided"),
    ("Reglement", "Instructions de demarrage dans le README",
     "tests/unit/test_contest_compliance.py::test_readme_contains_spin_up_instructions"),
    ("Reglement", "Materiaux de soumission en anglais",
     "tests/unit/test_contest_compliance.py::test_submission_material_is_in_english"),
    ("Reglement", "Le README expose la stack obligatoire",
     "tests/unit/test_contest_compliance.py::test_readme_states_the_mandatory_stack"),
    ("Reglement", "Video : 4 minutes et preuve Google Cloud",
     "tests/scenarios/test_demo_script.py::test_script_covers_the_video_requirements"),
    ("Reglement", "Le code source est en anglais",
     "tests/unit/test_contest_compliance.py::test_source_comments_are_in_english"),
]


def collected_node_ids() -> set[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--no-header"],
        cwd=ROOT, capture_output=True, text=True,
    )
    ids: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if "::" not in line:
            continue
        ids.add(line)
        ids.add(line.split("[")[0])  # tests parametres
    return ids


def main() -> int:
    available = collected_node_ids()
    missing: list[tuple[str, str, str]] = []

    current_doc = ""
    for doc, requirement, node_id in REQUIREMENTS:
        if doc != current_doc:
            print(f"\n{doc}")
            current_doc = doc
        covered = node_id in available
        if not covered:
            missing.append((doc, requirement, node_id))
        print(f"  {'✓' if covered else '✗'} {requirement}")
        if not covered:
            print(f"      test introuvable : {node_id}")

    total = len(REQUIREMENTS)
    print(f"\n{total - len(missing)}/{total} exigences couvertes par un test existant")
    if missing:
        print("\nExigences sans preuve :")
        for doc, requirement, node_id in missing:
            print(f"  - [{doc}] {requirement} -> {node_id}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
