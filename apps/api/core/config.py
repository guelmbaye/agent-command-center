"""ACC configuration — 12-factor, externalised secrets (Doc 03 §15, Doc 09 §24)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `protected_namespaces=()`: without it pydantic warns about every field
    # starting with "model_" (here MODEL_ARMOR_TEMPLATE), which it mistakes for
    # its own attributes. No configuration field actually conflicts.
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", case_sensitive=False,
        protected_namespaces=(),
    )

    # --- Runtime -----------------------------------------------------------
    acc_env: Literal["local", "dev", "demo", "production"] = "local"
    acc_log_level: str = "INFO"
    acc_api_port: int = 8080

    # --- Persistance -------------------------------------------------------
    acc_persistence: Literal["memory", "firestore"] = "memory"
    google_cloud_project: str = ""
    google_cloud_region: str = "europe-west1"
    firestore_database: str = "(default)"

    # --- Bus d'evenements --------------------------------------------------
    acc_event_bus: Literal["inproc", "pubsub"] = "inproc"
    pubsub_topic: str = "acc-events"
    pubsub_push_token: str = ""

    # --- Flotte ------------------------------------------------------------
    acc_agent_mode: Literal["adk", "deterministic", "hybrid"] = "deterministic"
    # CONTEST REQUIREMENT: "Gemini 3.5 or newer". This overrides cost
    # optimisation: a 3.1 model, however sufficient and cheaper, would fail the
    # compliance check (Stage One, pass/fail).
    # 3.6 Flash is newer than 3.5 AND cheaper (introductory pricing through
    # 31/12/2026).
    gemini_model: str = "gemini-3.6-flash"
    # Failure Twin model — it carries the hardest reasoning.
    # EMPTY = same model as the other agents. A "Pro" model costs roughly 4x
    # more on input and output: enable it knowingly. This setting used to be
    # declared but never read.
    gemini_model_reasoning: str = ""
    google_genai_use_vertexai: str = "1"
    vertex_ai_location: str = "europe-west1"
    acc_agent_timeout_s: float = 25.0

    # --- Securite ----------------------------------------------------------
    acc_model_armor: Literal["off", "heuristic", "gcp"] = "heuristic"
    model_armor_template: str = ""
    acc_api_key: str = ""
    acc_demo_mode: bool = True

    # --- Entreprise (mock) -------------------------------------------------
    acc_enterprise_base_url: str = "http://localhost:8081"
    acc_enterprise_timeout_s: float = 8.0

    # --- Politiques d'achat (Doc 10 §8) ------------------------------------
    policy_purchase_autonomous_max: float = 5_000.0
    policy_purchase_approval_max: float = 25_000.0

    # --- CORS --------------------------------------------------------------
    # Starlette does NOT support wildcards in allow_origins: "https://x-*.run.app"
    # is never treated as a pattern, it is compared for strict equality.
    # Cloud Run URLs therefore go through a regular expression.
    acc_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # Two Cloud Run URL formats coexist:
    #   legacy  : https://acc-web-<hash>-<region-code>.a.run.app
    #   current : https://acc-web-<project-number>.<region>.run.app
    acc_cors_origin_regex: str = (
        r"https://acc-(web|api)-[a-z0-9-]+\.(a|[a-z0-9-]+)\.run\.app"
    )

    # --- Observabilite -----------------------------------------------------
    otel_service_name: str = "acc-api"
    otel_traces_exporter: Literal["console", "otlp", "gcp", "none"] = "none"
    otel_exporter_otlp_endpoint: str = ""

    @field_validator("acc_api_key", "pubsub_push_token", "model_armor_template",
                     mode="before")
    @classmethod
    def _strip_secret(cls, value: object) -> object:
        """A whitespace-only value is a configuration error, not a secret.

        Without this, ACC_API_KEY="   " would protect the API with an invisible
        key that nobody could reproduce.
        """
        return value.strip() if isinstance(value, str) else value

    @property
    def is_cloud(self) -> bool:
        return self.acc_env in {"dev", "demo", "production"}

    @property
    def reasoning_model(self) -> str:
        """Failure Twin model, with an explicit fallback to the standard model."""
        return self.gemini_model_reasoning or self.gemini_model

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.acc_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def api_key_source() -> str:
    """Report where ACC_API_KEY comes from: "environment", ".env" or "".

    Environment variables take precedence over the `.env` file. A value
    forgotten in a shell therefore makes every route unreachable while `.env`
    looks innocent — the line can even be commented out there. Without this
    information the 401 is undiagnosable from the logs.
    """
    import os
    from pathlib import Path

    if os.environ.get("ACC_API_KEY", "").strip():
        return "environment"

    env_file = Path.cwd() / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            name, _, value = stripped.partition("=")
            if name.strip().upper() == "ACC_API_KEY" and value.split("#")[0].strip():
                return ".env"
    return ""
