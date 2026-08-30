"""Model Armor — guardrails on model interactions (Doc 03 §11-12).

Three modes:
  gcp        : Google Cloud Model Armor (sanitizeUserPrompt / sanitizeModelResponse)
  heuristic  : deterministic local detector — demo safety net (Level B)
  off        : disabled

Threats covered for the MVP: prompt injection, tool poisoning (tool output that
tries to redefine authority), sensitive data exposure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from apps.api.core.config import Settings, get_settings
from apps.api.core.logging import get_logger
from apps.api.core.telemetry import Span, span

logger = get_logger("acc.model_armor")

ThreatKind = Literal["PROMPT_INJECTION", "TOOL_POISONING", "SENSITIVE_DATA", "NONE"]

# Injection signatures: authority redefinition / approval bypass
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # Allow up to 3 interposed words: "ignore procurement policy",
    # "ignore all your previous instructions"... (otherwise we detect without
    # sanitising)
    (r"ignore\s+(?:\w+\s+){0,3}?(?:instructions?|polic(?:y|ies)|rules?|guardrails?)",
     "Attempt to neutralise instructions or policies"),
    (r"(?:ignorez?|oublie[sz]?)\s+(?:\w+\s+){0,3}?(?:politiques?|consignes?|instructions?|regles?)",
     "Attempt to neutralise instructions (French wording)"),
    (r"do\s+not\s+request\s+approval|skip\s+(?:the\s+)?approval|bypass\s+(?:the\s+)?(?:approval|policy)",
     "Attempt to bypass human approval"),
    (r"sans\s+demander\s+d[e']?\s*approbation|ne\s+demande[sz]?\s+pas\s+d[e']?\s*approbation",
     "Attempt to bypass human approval (French wording)"),
    (r"execute\s+immediately|purchase\s+immediately|transfer\s+funds",
     "Order to execute a consequential action immediately"),
    (r"you\s+are\s+now\s+|act\s+as\s+(?:an?\s+)?(?:admin|root|system)",
     "Attempt to redefine role or privileges"),
    (r"reveal\s+(?:your\s+)?(?:system\s+prompt|instructions|api\s*key)",
     "Attempt to exfiltrate system instructions"),
]

_SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    (r"AIza[0-9A-Za-z\-_]{20,}", "Cle API Google detectee"),
    (r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----", "Cle privee detectee"),
    (r"\bsk-[A-Za-z0-9]{20,}\b", "Jeton secret detecte"),
    (r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", "Numero de carte potentiel"),
]


@dataclass
class ArmorVerdict:
    blocked: bool
    threat: ThreatKind = "NONE"
    reasons: list[str] = field(default_factory=list)
    sanitized: str = ""
    provider: str = "heuristic"
    raw_state: str | None = None

    @property
    def detail(self) -> str:
        return " | ".join(self.reasons) if self.reasons else "No threat detected"


class ModelArmor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._gcp_client = None

    # --- Public API --------------------------------------------------------
    async def scan_prompt(self, text: str, source: str = "user") -> ArmorVerdict:
        return await self._scan(text, direction="prompt", source=source)

    async def scan_tool_output(self, text: str, tool: str) -> ArmorVerdict:
        """Tool poisoning: tool output is untrusted content."""
        return await self._scan(text, direction="tool_output", source=tool)

    async def scan_model_response(self, text: str) -> ArmorVerdict:
        return await self._scan(text, direction="model_response", source="model")

    # --- Implementation ----------------------------------------------------
    async def _scan(self, text: str, direction: str, source: str) -> ArmorVerdict:
        mode = self.settings.acc_model_armor
        if mode == "off" or not text:
            return ArmorVerdict(blocked=False, sanitized=text, provider="off")

        with span(Span.ARMOR_SCAN, direction=direction, source=source):
            if mode == "gcp":
                verdict = await self._scan_gcp(text, direction)
                if verdict is not None:
                    return verdict
                logger.warning("model_armor_gcp_unavailable_fallback_heuristic")
            return self._scan_heuristic(text, direction, source)

    def _scan_heuristic(self, text: str, direction: str, source: str) -> ArmorVerdict:
        lowered = text.lower()
        reasons: list[str] = []
        threat: ThreatKind = "NONE"

        for pattern, label in _INJECTION_PATTERNS:
            if re.search(pattern, lowered, flags=re.IGNORECASE):
                reasons.append(label)
                threat = "TOOL_POISONING" if direction == "tool_output" else "PROMPT_INJECTION"

        sensitive: list[str] = []
        for pattern, label in _SENSITIVE_PATTERNS:
            if re.search(pattern, text):
                sensitive.append(label)
        if sensitive and threat == "NONE":
            threat = "SENSITIVE_DATA"
        reasons.extend(sensitive)

        blocked = bool(reasons)
        sanitized = text
        if blocked:
            sanitized = self._sanitize(text)
            logger.warning("model_armor_threat", extra={
                "threat": threat, "direction": direction, "source": source,
                "reasons": reasons,
            })
        return ArmorVerdict(blocked=blocked, threat=threat, reasons=reasons,
                            sanitized=sanitized, provider="heuristic")

    @staticmethod
    def _sanitize(text: str) -> str:
        out = text
        for pattern, _ in _INJECTION_PATTERNS:
            out = re.sub(pattern, "[UNTRUSTED CONTENT NEUTRALISED]", out, flags=re.IGNORECASE)
        for pattern, _ in _SENSITIVE_PATTERNS:
            out = re.sub(pattern, "[REDACTED]", out)
        return out

    async def _scan_gcp(self, text: str, direction: str) -> ArmorVerdict | None:  # pragma: no cover
        template = self.settings.model_armor_template
        if not template:
            return None
        try:
            from google.cloud import modelarmor_v1

            if self._gcp_client is None:
                region = self.settings.google_cloud_region
                self._gcp_client = modelarmor_v1.ModelArmorAsyncClient(
                    client_options={"api_endpoint": f"modelarmor.{region}.rep.googleapis.com"}
                )
            client = self._gcp_client
            data = modelarmor_v1.DataItem(text=text)
            if direction == "model_response":
                response = await client.sanitize_model_response(
                    request=modelarmor_v1.SanitizeModelResponseRequest(
                        name=template, model_response_data=data)
                )
            else:
                response = await client.sanitize_user_prompt(
                    request=modelarmor_v1.SanitizeUserPromptRequest(
                        name=template, user_prompt_data=data)
                )
            result = response.sanitization_result
            state = str(result.filter_match_state)
            blocked = "MATCH_FOUND" in state and "NO_MATCH_FOUND" not in state
            reasons = [
                f"{name}: {getattr(res, 'match_state', '')}"
                for name, res in (result.filter_results or {}).items()
            ] if blocked else []
            return ArmorVerdict(
                blocked=blocked,
                threat="PROMPT_INJECTION" if blocked else "NONE",
                reasons=reasons or (["Model Armor a signale une correspondance"] if blocked else []),
                sanitized=self._sanitize(text) if blocked else text,
                provider="gcp", raw_state=state,
            )
        except Exception as exc:
            logger.error("model_armor_gcp_error", extra={"detail": str(exc)})
            return None
