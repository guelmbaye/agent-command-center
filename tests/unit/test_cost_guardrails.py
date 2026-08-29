"""Cost guardrails.

With a fixed budget (hackathon credits), an expensive default or a service that
bills while idle is discovered on the invoice.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import make_settings

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = "\n".join(
    p.read_text(encoding="utf-8")
    for p in sorted((ROOT / "infrastructure" / "terraform").glob("*.tf"))
)


def test_no_agent_uses_a_pro_model_by_default():
    """A "Pro" model costs roughly 4x more: never by default."""
    settings = make_settings()
    assert settings.gemini_model_reasoning == "", (
        "le modèle de raisonnement doit être vide par défaut"
    )
    assert settings.reasoning_model == settings.gemini_model
    assert "pro" not in settings.gemini_model.lower()


def test_reasoning_model_is_actually_wired():
    """Regression: this setting was declared but never read.

    A button that does nothing is worse than no button: it gives the illusion
    of a control.
    """
    from apps.api.repositories.factory import reset_store
    from apps.api.services.container import build_container

    reset_store()
    # Arbitrary value: the test checks the WIRING, not a model name. Hardcoding
    # a real identifier here would make it wrong at the next retirement.
    marker = "modele-de-raisonnement-distinct"
    settings = make_settings(gemini_model_reasoning=marker)
    container = build_container(settings)
    assert container.runtime.get("failure-twin").model == marker
    assert container.runtime.get("supply-agent").model == settings.gemini_model
    reset_store()


def test_every_cloud_run_service_scales_to_zero():
    """A minimum instance count > 0 bills even while idle."""
    minimums = re.findall(r"min_instance_count\s*=\s*(\S+)", TERRAFORM)
    assert minimums, "aucun min_instance_count déclaré"
    for value in minimums:
        assert value == "0", f"min_instance_count = {value} facture à l'inactivité"


def test_every_cloud_run_service_has_an_instance_ceiling():
    services = TERRAFORM.count("resource \"google_cloud_run_v2_service\"")
    ceilings = len(re.findall(r"max_instance_count", TERRAFORM))
    assert ceilings >= services, "un service sans plafond peut s'emballer"


@pytest.mark.parametrize("expensive", [
    "google_container_cluster",      # GKE facture en continu
    "google_sql_database_instance",  # Cloud SQL idem
    "google_redis_instance",
    "google_compute_instance",
    "google_vertex_ai_endpoint",     # un endpoint deployé facture à l'heure
])
def test_no_continuously_billing_resource(expensive):
    """Items that bill by the hour rather than by usage are excluded."""
    assert expensive not in TERRAFORM


def test_firestore_is_protected_against_accidental_deletion():
    assert "delete_protection_state" in TERRAFORM


def test_cost_labels_allow_billing_breakdown():
    """Without labels, ACC spend cannot be isolated in the invoice."""
    assert "cost_labels" in TERRAFORM
    assert re.search(r'app\s*=\s*"acc"', TERRAFORM)


def test_agent_timeout_is_bounded():
    """An unbounded model call can consume without end."""
    settings = make_settings()
    assert 0 < settings.acc_agent_timeout_s <= 60


def test_retry_budget_is_bounded():
    """An unbounded recovery loop would multiply model calls."""
    from domain.models import Task

    assert Task(mission_id="M", type="t").max_attempts <= 5


# ---------------------------------------------------------------------------
# Model lifecycle
#
# The initial default `gemini-2.5-flash` retires on 16 October 2026. It would
# have worked during the hackathon, then returned 404 if evaluation ran into
# October — a silent failure, after submission.
# ---------------------------------------------------------------------------
RETIRING_MODELS = {
    # id -> announced retirement date
    "gemini-2.5-pro": "2026-10-16",
    "gemini-2.5-flash": "2026-10-16",
    "gemini-2.5-flash-lite": "2026-10-16",
    "gemini-2.5-flash-image": "2026-10-02",
    "gemini-2.0-flash": "2026-06-01 (already retired)",
    "gemini-2.0-flash-lite": "2026-06-01 (already retired)",
}

CONFIG_FILES = [
    ROOT / "apps" / "api" / "core" / "config.py",
    ROOT / ".env.example",
    ROOT / "infrastructure" / "terraform" / "variables.tf",
]


@pytest.mark.parametrize("path", CONFIG_FILES, ids=lambda p: p.name)
def test_no_retiring_model_is_configured(path):
    """No default may point at an end-of-life model."""
    text = path.read_text(encoding="utf-8")
    for model, eol in RETIRING_MODELS.items():
        # The name may appear in an explanatory comment; only real assignments
        # are rejected.
        assignments = re.findall(
            rf'(?:=|default\s*=)\s*"{re.escape(model)}"', text
        )
        assert not assignments, (
            f"{path.name} configure {model}, retiré le {eol}"
        )


def test_configured_model_is_current_generation():
    settings = make_settings()
    assert settings.gemini_model not in RETIRING_MODELS
    assert settings.gemini_model.startswith("gemini-3."), (
        f"{settings.gemini_model} n'est pas de génération courante"
    )


def test_no_hardwired_sampling_parameters():
    """temperature / top_p / top_k have been deprecated since 21 July 2026.

    Hardwiring them is the usual blocker when switching models. ACC sets none
    of them: changing model is a single environment variable.
    """
    for source in (ROOT / "agents").rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for banned in ("temperature=", "top_p=", "top_k="):
            assert banned not in code, f"{source.name} câble {banned}"
