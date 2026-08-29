"""Outillage de developpement : portabilite Windows / macOS / Linux.

Regression : le Makefile utilisait « VAR=valeur commande », syntaxe propre aux
shells POSIX. Sous Windows, make delegue a cmd.exe qui repond
"'ACC_ENTERPRISE_BASE_URL' is not recognized". Every target now goes through
scripts/dev.py.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")

# A make recipe starts with a tab.
RECIPES = [line for line in MAKEFILE.splitlines() if line.startswith("\t")]


def test_no_posix_env_assignment_in_recipes():
    """'VAR=value command' breaks under cmd.exe."""
    offenders = [r for r in RECIPES if re.match(r"\t\s*[A-Za-z_][A-Za-z0-9_]*=", r)]
    assert not offenders, (
        "Affectation de variable en prefixe de commande (POSIX seulement) : "
        f"{offenders}"
    )


def test_no_line_continuation_in_recipes():
    """A trailing backslash produces a truncated command under cmd.exe."""
    offenders = [r for r in RECIPES if r.rstrip().endswith("\\")]
    assert not offenders, f"Continuation de ligne dans une recette : {offenders}"


def test_no_posix_only_operators_in_recipes():
    """Constructs absent from cmd.exe.

    Note: "&&" is NOT in this list — cmd.exe supports it. A first version of
    this test rejected it, which would have forced working around an inaccurate
    rule rather than fixing a real portability defect.
    """
    posix_only = ("`", "||", "export ", "source ", "$(pwd)", "${")
    offenders = [r for r in RECIPES if any(t in r for t in posix_only)]
    assert not offenders, f"Construction absente de cmd.exe : {offenders}"


def test_npm_is_never_invoked_directly():
    """On Windows npm is a .cmd: the launcher resolves it via shutil.which."""
    offenders = [r for r in RECIPES if "npm " in r]
    assert not offenders, (
        f"Appel npm direct dans le Makefile : {offenders}. "
        "Passer par scripts/dev.py."
    )


@pytest.mark.parametrize("target", [
    "run:", "run-mock:", "web:", "web-build:", "doctor:", "scenario:", "audit:",
])
def test_expected_targets_exist(target):
    assert f"\n{target}" in MAKEFILE


def test_ports_are_overridable():
    """'make run PORT=8099' must work: 8080 is often taken."""
    for variable in ("PORT ?=", "MOCK_PORT ?=", "ACC_API ?="):
        assert variable in MAKEFILE


def test_dev_launcher_exposes_every_command():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "acc_dev", ROOT / "scripts" / "dev.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name in ("serve_api", "serve_mock", "serve_web", "build_web"):
        assert hasattr(module, name)


def test_launcher_uses_the_current_interpreter():
    """sys.executable: works inside a Windows venv with no special PATH."""
    source = (ROOT / "scripts" / "dev.py").read_text(encoding="utf-8")
    assert "sys.executable" in source
    # npm is a .cmd on Windows: shutil.which is essential.
    assert "shutil.which" in source


def test_api_launcher_propagates_the_mock_port():
    source = (ROOT / "scripts" / "dev.py").read_text(encoding="utf-8")
    assert "ACC_ENTERPRISE_BASE_URL" in source
    assert "args.mock_port" in source


def test_launcher_propagates_the_backend_api_key(monkeypatch, tmp_path):
    """One source of truth for the key.

    Regression: `ACC_API_KEY` (backend) and `NEXT_PUBLIC_ACC_API_KEY` (frontend)
    lived in two unlinked files. Any divergence produced 401s on every route,
    with no clue as to the cause.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("acc_dev", ROOT / "scripts" / "dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "_backend_api_key", lambda: "cle-du-backend")
    monkeypatch.delenv("NEXT_PUBLIC_ACC_API_KEY", raising=False)

    env = module._web_env("http://127.0.0.1:8080")
    assert env["NEXT_PUBLIC_ACC_API"] == "http://127.0.0.1:8080"
    assert env["NEXT_PUBLIC_ACC_API_KEY"] == "cle-du-backend"


def test_launcher_respects_an_explicit_frontend_key(monkeypatch):
    """An explicitly provided value is never overwritten."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("acc_dev", ROOT / "scripts" / "dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "_backend_api_key", lambda: "cle-du-backend")
    monkeypatch.setenv("NEXT_PUBLIC_ACC_API_KEY", "cle-explicite")

    assert module._web_env("http://x")["NEXT_PUBLIC_ACC_API_KEY"] == "cle-explicite"


def test_port_holders_decodes_defensively():
    """On Windows, netstat output is not valid cp1252.

    Regression: `subprocess.run(..., text=True)` decodes with the local encoding
    and raises UnicodeDecodeError inside a reader thread — the diagnostic
    crashed before diagnosing anything at all.
    """
    source = (ROOT / "scripts" / "doctor.py").read_text(encoding="utf-8")
    # Look at CODE only: the explanatory comment mentions text=True.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert 'errors="replace"' in code or "errors='replace'" in code
    assert "text=True" not in code, (
        "decoder explicitement en utf-8 tolerant, sans dependre de la locale"
    )


def test_doctor_treats_missing_enterprise_as_blocking():
    """An "all clear" in front of a system that cannot work is worse than no
    diagnostic at all."""
    source = (ROOT / "scripts" / "doctor.py").read_text(encoding="utf-8")
    assert "acc_running" in source
    assert "no mission can complete" in source


# ---------------------------------------------------------------------------
# Failure attribution
#
# Usage regression: the Supply Agent was marked DEGRADED every time a supplier
# was unavailable. It had nonetheless done its job perfectly — detect and report
# the outage. In fleet health that points the operator at the wrong problem.
# ---------------------------------------------------------------------------
import pytest as _pytest


@_pytest.mark.parametrize("failure_class,degrades", [
    ("DEPENDENCY", False),     # the supplier is dead, not the agent
    ("PERMANENT", False),      # insufficient resource: a correct observation
    ("AUTHORIZATION", False),  # policy denial: governance, not malfunction
    ("SECURITY", False),       # threat blocked: the agent reacted correctly
    ("AGENT", True),           # the agent itself failed
    ("TIMEOUT", True),         # the agent did not answer
    ("UNKNOWN", True),         # caution: unknown cause
])
def test_only_agent_faults_degrade_the_agent(failure_class, degrades):
    from agents.contracts import failure_result
    from agents.runtime import _indicts_the_agent
    from domain.enums import FailureClass

    result = failure_result("x", FailureClass(failure_class))
    assert _indicts_the_agent(result) is degrades


def test_a_successful_execution_never_degrades():
    from agents.runtime import _indicts_the_agent
    from domain.models import AgentResult

    assert _indicts_the_agent(AgentResult()) is False
