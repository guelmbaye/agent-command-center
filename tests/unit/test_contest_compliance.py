"""Contest rules compliance (Stage One: pass/fail).

These are not preferences: a single unmet requirement eliminates the submission
before any qualitative evaluation. So they are tested.

Source: https://allthingsagentichackathon.devpost.com/rules
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.conftest import make_settings

ROOT = Path(__file__).resolve().parents[2]

# « Mandatory for all categories: 1) Gemini 3.5 or newer »
MINIMUM_GEMINI = (3, 5)


def _version(model: str) -> tuple[int, int] | None:
    match = re.search(r"gemini-(\d+)\.(\d+)", model)
    return (int(match.group(1)), int(match.group(2))) if match else None


def test_configured_model_meets_the_mandatory_minimum():
    """Regression: `gemini-3.1-flash-lite` had been chosen for its cost.

    3.1 < 3.5: the choice was cheaper and technically sufficient, but would
    have failed the compliance check.
    """
    model = make_settings().gemini_model
    version = _version(model)
    assert version is not None, f"version illisible dans « {model} »"
    assert version >= MINIMUM_GEMINI, (
        f"{model} : le concours exige Gemini 3.5 ou plus récent"
    )


@pytest.mark.parametrize("path", [
    ROOT / "apps" / "api" / "core" / "config.py",
    ROOT / ".env.example",
    ROOT / "infrastructure" / "terraform" / "variables.tf",
], ids=lambda p: p.name)
def test_no_file_configures_a_non_compliant_model(path):
    text = path.read_text(encoding="utf-8")
    for assigned in re.findall(r'(?:=|default\s*=)\s*"(gemini-[^"]+)"', text):
        version = _version(assigned)
        assert version is not None and version >= MINIMUM_GEMINI, (
            f"{path.name} configure {assigned}, non conforme (< 3.5)"
        )


def test_mandatory_google_stack_is_present():
    """« at least one Google Agent Framework » + « one Google Cloud service »."""
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "google-adk" in requirements, "framework d'agent Google requis"

    terraform = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (ROOT / "infrastructure" / "terraform").glob("*.tf")
    )
    for service in ("google_cloud_run_v2_service", "google_firestore_database",
                    "google_pubsub_topic"):
        assert service in terraform, f"{service} attendu dans l'infrastructure"


def test_fortified_fleet_primitives_are_all_implemented():
    """The seven primitives required by the Fortified Enterprise Fleet track."""
    modules = {
        "Agent Registry": ROOT / "apps/api/services/registry.py",
        "Agent Runtime": ROOT / "agents/runtime.py",
        "Memory Bank": ROOT / "apps/api/services/memory_service.py",
        "Agent Identity": ROOT / "domain/models.py",
        "Agent Gateway": ROOT / "apps/api/services/agent_gateway.py",
        "Model Armor": ROOT / "apps/api/services/model_armor.py",
        "Agent Observability": ROOT / "apps/api/core/telemetry.py",
    }
    for primitive, path in modules.items():
        assert path.exists(), f"{primitive} : {path.name} introuvable"


def test_architecture_diagram_is_provided():
    """« Include an Architecture Diagram » — exigence de soumission."""
    diagrams = list((ROOT / "docs" / "diagrams").glob("*.mmd"))
    assert diagrams, "aucun schéma d'architecture fourni"


def test_readme_contains_spin_up_instructions():
    """« Spin-up Instructions: A step-by-step guide in your README.md »."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "pip install -r requirements.txt" in readme
    assert "deploy" in readme.lower()


# ---------------------------------------------------------------------------
# « The Application must, at a minimum, support English language use »
#
# The product was developed in French. This requirement covers what the user —
# here the judges — sees: interface labels, event messages, agent findings,
# decision reasons.
# ---------------------------------------------------------------------------
ACCENTS = "éèêëàâçùûôîïœ"

# Accent-free French slips through an accent check. `"Cle d'API invalide ou
# absente"` reached production that way: no accent, and its file was not in the
# list below. Both gaps are closed.
FRENCH_PHRASES = (
    "cle d'api", "invalide ou absente", "introuvable", "echec", "aucune",
    "impossible de", "n'est pas", "veuillez", "erreur", "interdit",
    "requete", "prete", "reinitialis", "demarrer", "panne", "systemes",
    "selectionne", "diagnostique", "menace", "etat acc",
    "tentative", "injonction", "neutralisation", "contournement",
    "exfiltration", "redefinition", "consequente", "contexte", "injecte",
)

USER_FACING_BACKEND = [
    ROOT / "apps/api/services/mission_engine.py",
    ROOT / "apps/api/services/recovery_engine.py",
    ROOT / "apps/api/services/approval_service.py",
    ROOT / "apps/api/services/checkpoint_service.py",
    ROOT / "apps/api/services/policy_engine.py",
    ROOT / "apps/api/services/agent_gateway.py",
    ROOT / "apps/api/services/registry.py",
    ROOT / "domain/plans.py",
    ROOT / "apps/api/main.py",
    ROOT / "apps/api/core/config.py",
    ROOT / "apps/api/routes/deps.py",
    ROOT / "apps/api/routes/missions.py",
    ROOT / "apps/api/routes/demo.py",
    ROOT / "apps/api/core/errors.py",
    ROOT / "domain/errors.py",
    ROOT / "apps/api/routes/health.py",
    ROOT / "apps/api/routes/approvals.py",
    ROOT / "apps/api/routes/agents.py",
    ROOT / "apps/api/routes/events.py",
    ROOT / "apps/api/routes/metrics.py",
    ROOT / "mock_enterprise/main.py",
    ROOT / "apps/api/services/model_armor.py",
    ROOT / "apps/api/services/alerting.py",
    ROOT / "apps/api/services/enterprise_tools.py",
    ROOT / "agents/base.py",
    ROOT / "agents/runtime.py",
    ROOT / "domain/state_machine.py",
    ROOT / "agents/supply/agent.py",
    ROOT / "agents/risk/agent.py",
    ROOT / "agents/procurement/agent.py",
    ROOT / "agents/failure_twin/agent.py",
]


def _has_french_phrase(line: str) -> bool:
    """Match whole words only.

    Substring matching flagged `logger.warning("demo_supplier_failure_injected")`
    on the French "injecte". A detector that cries wolf is a detector the next
    reader disables.
    """
    lowered = line.lower()
    return any(
        re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", lowered)
        for phrase in FRENCH_PHRASES
    )


def _code_only(text: str) -> list[tuple[int, str]]:
    """Keep only displayed lines: comments are not UI.

    Covers Python docstrings, `#` comments, and TypeScript `/** */` blocks and
    `//` lines.
    """
    out, in_doc, in_block = [], False, False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_doc = not in_doc
            continue
        if stripped.startswith("/*"):
            in_block = not stripped.endswith("*/")
            continue
        if in_block:
            if stripped.endswith("*/"):
                in_block = False
            continue
        if in_doc or stripped.startswith(("#", "*", "//")):
            continue
        out.append((number, line))
    return out


@pytest.mark.parametrize("path", USER_FACING_BACKEND, ids=lambda p: p.name)
def test_backend_user_facing_strings_are_english(path):
    offenders = [
        (number, line.strip()[:80])
        for number, line in _code_only(path.read_text(encoding="utf-8"))
        if any(a in line for a in ACCENTS) or _has_french_phrase(line)
    ]
    assert not offenders, f"{path.name}: non-English text {offenders[:3]}"


def test_ui_strings_are_english():
    web = ROOT / "apps" / "web"
    offenders = []
    for path in list(web.glob("components/*.tsx")) + list(web.glob("app/*.tsx")) \
            + list(web.glob("lib/*.ts")):
        for number, line in _code_only(path.read_text(encoding="utf-8")):
            if line.strip().startswith("//"):
                continue
            if any(a in line for a in ACCENTS):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"interface non anglaise : {offenders[:5]}"


def test_html_lang_is_english():
    layout = (ROOT / "apps/web/app/layout.tsx").read_text(encoding="utf-8")
    assert 'lang="en"' in layout


# ---------------------------------------------------------------------------
# « All Submission materials must be in English »
#
# The project was developed in French. These files are the ones the judges
# read: they must stay in English, including after any later addition.
# ---------------------------------------------------------------------------
SUBMISSION_MATERIALS = [
    ROOT / "README.md",
    ROOT / "docs" / "DEMO_SCRIPT.md",
    ROOT / "DEPLOYMENT.md",
    ROOT / "docs" / "ARCHITECTURE.md",
]


@pytest.mark.parametrize("path", SUBMISSION_MATERIALS, ids=lambda p: p.name)
def test_submission_material_is_in_english(path):
    offenders = [
        f"{n}: {line.strip()[:70]}"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if any(a in line for a in ACCENTS)
    ]
    assert not offenders, f"{path.name} contient du texte non anglais : {offenders[:3]}"


def test_readme_states_the_mandatory_stack():
    """The judges must find compliance without reading the code."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for expected in ("Gemini 3.5 or newer", "Google ADK", "Cloud Run", "Firestore"):
        assert expected in readme, f"le README doit mentionner : {expected}"


def test_readme_points_to_the_architecture_diagram():
    """The rendered file is what a judge opens; the source is for maintainers."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/diagrams/architecture.png" in readme
    assert "architecture.mmd" in readme, "keep the maintained source visible"


def test_no_dangling_reference_to_the_renamed_guide():
    """The French guide DEMARRAGE.md became DEPLOYMENT.md."""
    for path in (ROOT / "README.md", ROOT / "docs" / "DEMO_SCRIPT.md"):
        assert "DEMARRAGE" not in path.read_text(encoding="utf-8")
    assert (ROOT / "DEPLOYMENT.md").exists()
    assert not (ROOT / "DEMARRAGE.md").exists()


def test_every_adr_is_numbered_and_indexed():
    """The ADRs serve the "Architectural Discipline" criterion (30 %)."""
    text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    headings = re.findall(r"^## ADR-(\d{3}) — (.+)$", text, re.MULTILINE)
    assert len(headings) >= 37, f"seulement {len(headings)} ADR"

    numbers = [int(n) for n, _ in headings]
    assert numbers == sorted(numbers), "ADR non ordonnes"
    assert len(set(numbers)) == len(numbers), "numero d'ADR duplique"

    # Every ADR must appear in the top index, otherwise it is invisible.
    index = text.split("## ADR-001")[0]
    for number, _ in headings:
        assert f"| {int(number):03d} |" in index or f"| {int(number)} |" in index, (
            f"ADR-{number} absent de l'index"
        )


# ---------------------------------------------------------------------------
# The source code itself is part of the "materials submitted".
#
# Detection uses function words, not accents: many French comments were written
# without accents and slipped under the radar.
# ---------------------------------------------------------------------------
FRENCH_MARKERS = {
    "le", "la", "les", "une", "des", "qui", "que", "dont", "pour", "dans",
    "sans", "avec", "donc", "mais", "est", "sont", "pas", "plus", "tout",
    "son", "ses", "leur", "elle", "sur", "sous", "entre", "chaque", "aucun",
    "jamais", "toujours", "doit", "peut", "ainsi", "alors", "apres", "avant",
    "depuis", "cela", "celui", "etat", "echec", "tache", "cle", "meme",
}


def _comment_lines(text: str):
    """Docstrings and comments only — code is not prose."""
    inside = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.count('"""') == 1:
            inside = not inside
            yield number, stripped
            continue
        if inside or stripped.startswith("#"):
            yield number, stripped


# A line made only of quoted literals is DATA (for instance the FRENCH_MARKERS
# list itself), not prose.
_DATA_LINE = re.compile(r'^\s*(?:"[a-z_]+",\s*)+$')


def _french_score(line: str) -> int:
    if _DATA_LINE.match(line):
        return 0
    words = set(re.findall(r"[a-zA-Z]+", line.lower()))
    return len(words & FRENCH_MARKERS)


SOURCE_DIRS = ["apps", "agents", "domain", "mock_enterprise", "scripts", "tests"]


@pytest.mark.parametrize("directory", SOURCE_DIRS)
def test_source_comments_are_in_english(directory):
    offenders = []
    for path in sorted((ROOT / directory).rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for number, line in _comment_lines(text):
            if _french_score(line) >= 3 or any(a in line for a in ACCENTS):
                offenders.append(f"{path.relative_to(ROOT)}:{number}  {line[:60]}")
    assert not offenders, (
        f"{len(offenders)} non-English line(s): " + "; ".join(offenders[:4])
    )


def test_the_architecture_diagram_is_an_uploadable_file():
    """Devpost requires the diagram UPLOADED: pdf/ppt/pptx/png/jpg — not .mmd."""
    diagrams = ROOT / "docs" / "diagrams"
    rendered = [p for p in diagrams.iterdir()
                if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}]
    assert rendered, (
        "only Mermaid sources are present; the submission form cannot take them"
    )
    assert any(p.stat().st_size > 20_000 for p in rendered), "diagram looks empty"


def test_the_submission_sheet_declares_a_compliant_model():
    """The form asks for the model, and Stage One checks it."""
    submission = (ROOT / "docs" / "SUBMISSION.md").read_text(encoding="utf-8")
    model = make_settings().gemini_model
    assert model in submission, (
        f"the submission sheet must name the model actually deployed ({model})"
    )
    assert "Fortified Enterprise Fleet" in submission
    assert "Google ADK" in submission


def test_the_submission_sheet_respects_the_field_limits():
    import re as _re

    text = (ROOT / "docs" / "SUBMISSION.md").read_text(encoding="utf-8")
    name = _re.search(r"## Project name.*?```\n(.*?)\n```", text, _re.S).group(1)
    pitch = _re.search(r"## Elevator pitch.*?```\n(.*?)\n```", text, _re.S).group(1)
    tags = _re.search(r"## Built with.*?```\n(.*?)\n```", text, _re.S).group(1)

    assert len(name) <= 60, f"project name is {len(name)} characters"
    assert len(pitch) <= 200, f"elevator pitch is {len(pitch)} characters"
    assert len([t for t in _re.split(r"[,\s]+", tags) if t]) <= 25
