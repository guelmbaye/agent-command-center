"""Configuration provenance — the env / .env precedence trap.

Regression: a `.env` with `#ACC_API_KEY=` (commented out) suggested no key was
configured, while an environment variable forgotten in the shell made every
route unreachable. The logs said "missing or invalid key" without ever
indicating where the key came from.
"""
from __future__ import annotations

import pytest

from apps.api.core.config import Settings, api_key_source


def write_env(tmp_path, content: str, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return env_file


def test_commented_key_is_not_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ACC_API_KEY", raising=False)
    write_env(tmp_path, "#ACC_API_KEY=secret\nACC_ENV=local\n", monkeypatch)
    assert Settings().acc_api_key == ""
    assert api_key_source() == ""


def test_environment_variable_wins_over_dotenv(tmp_path, monkeypatch):
    """The exact trap: .env commented out, but an environment variable active."""
    write_env(tmp_path, "#ACC_API_KEY=\nACC_ENV=local\n", monkeypatch)
    monkeypatch.setenv("ACC_API_KEY", "fantome")

    assert Settings().acc_api_key == "fantome"
    assert api_key_source() == "environment", (
        "La source doit etre identifiee, sinon le 401 est indiagnosticable"
    )


def test_dotenv_key_is_reported_as_such(tmp_path, monkeypatch):
    monkeypatch.delenv("ACC_API_KEY", raising=False)
    write_env(tmp_path, "ACC_API_KEY=depuis-le-fichier\n", monkeypatch)
    assert Settings().acc_api_key == "depuis-le-fichier"
    assert api_key_source() == ".env"


def test_inline_comments_are_stripped(tmp_path, monkeypatch):
    """The shipped .env contains trailing inline comments."""
    monkeypatch.delenv("ACC_API_KEY", raising=False)
    write_env(
        tmp_path,
        "ACC_ENV=local                  # local | dev | demo | production\n"
        "ACC_AGENT_MODE=deterministic   # adk | deterministic | hybrid\n"
        "ACC_MODEL_ARMOR=heuristic      # off | heuristic | gcp\n",
        monkeypatch,
    )
    settings = Settings()
    assert settings.acc_env == "local"
    assert settings.acc_agent_mode == "deterministic"
    assert settings.acc_model_armor == "heuristic"


def test_empty_assignment_is_not_a_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ACC_API_KEY", raising=False)
    write_env(tmp_path, "ACC_API_KEY=                # commentaire\n", monkeypatch)
    assert api_key_source() == ""


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_environment_value_is_not_a_key(monkeypatch, value):
    monkeypatch.setenv("ACC_API_KEY", value)
    assert api_key_source() in ("", ".env")
